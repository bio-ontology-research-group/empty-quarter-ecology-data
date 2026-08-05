@Grab(group='org.apache.poi', module='poi-ooxml', version='5.2.5')
import org.apache.poi.ss.usermodel.*
import org.apache.poi.xssf.usermodel.XSSFWorkbook
import java.io.File

def excelFile = new File("data/metadata/samples/Sample_Mastersheet.xlsx")
FileInputStream fis = new FileInputStream(excelFile)
Workbook workbook = new XSSFWorkbook(fis)
Sheet sheet = workbook.getSheetAt(0)
Row headerRow = sheet.getRow(0)
println "Sheet: ${sheet.getSheetName()}"
headerRow.each { cell -> print "[${cell.getStringCellValue()}] " }
println ""
