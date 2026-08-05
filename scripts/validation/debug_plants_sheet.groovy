@Grab(group='org.apache.poi', module='poi-ooxml', version='5.2.5')
import org.apache.poi.ss.usermodel.*
import org.apache.poi.xssf.usermodel.XSSFWorkbook
import java.io.File

def excelFile = new File("data/metadata/samples/Sample_Mastersheet.xlsx")
FileInputStream fis = new FileInputStream(excelFile)
Workbook workbook = new XSSFWorkbook(fis)
Sheet sheet = workbook.getSheet("Plants")
if (!sheet) {
    println "Sheet 'Plants' not found."
    return
}
Row headerRow = sheet.getRow(0)
println "Headers:"
headerRow.each { cell -> print "[${cell.getStringCellValue()}] " }
println "\nFirst 5 rows:"
(1..5).each {
    idx ->
    Row row = sheet.getRow(idx)
    if (row) {
        row.each { cell -> print "[${cell.toString()}] " }
        println ""
    }
}

